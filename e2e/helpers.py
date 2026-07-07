"""Shared e2e helpers: build the browser+token side of a signing round trip
and inspect the signed bytes the server returns.

The "sign a hash" functions play the role signer-host plays with a real token:
they return CMS-ready signature values (PKCS#1 v1.5 for RSA, DER ECDSA-Sig-Value
for EC), byte-identical to what the host produces over PKCS#11.
"""

import base64
import datetime
import io
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from cryptography.x509.oid import NameOID


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def unb64(s: str) -> bytes:
    return base64.b64decode(s)


_HASHES = {"sha256": hashes.SHA256, "sha384": hashes.SHA384, "sha512": hashes.SHA512}


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def make_signer_cert(key_type: str = "rsa", cn: str | None = None):
    """A self-signed signer cert carrying the PII from the e2e env.

    Returns (private_key, cert_der). Self-signed is enough for B-B/B-T and for
    every structural/validity check; profiles that embed revocation (B-LT and
    up, CCA-*) need a CA-issued cert with a reachable OCSP/CRL, i.e. the real
    DSC token — those cases skip in the sandbox.
    """
    if key_type == "ec":
        key = ec.generate_private_key(ec.SECP256R1())
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, env("E2E_SIGNER_COUNTRY", "IN")),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, env("E2E_SIGNER_ORG", "OpenSigner Tests")),
            x509.NameAttribute(NameOID.COMMON_NAME, cn or env("E2E_SIGNER_CN", "Test Signer")),
        ]
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=False,
            crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
    )
    email = env("E2E_SIGNER_EMAIL")
    if email:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.RFC822Name(email)]), critical=False)
    cert = builder.sign(key, hashes.SHA256())
    return key, cert.public_bytes(serialization.Encoding.DER)


def sign_hash(key, digest_b64: str, digest_algorithm: str = "sha256") -> str:
    """Sign one server-returned to_sign_hash, CMS-ready, base64 out."""
    digest = unb64(digest_b64)
    algo = _HASHES[digest_algorithm]()
    if isinstance(key, ec.EllipticCurvePrivateKey):
        sig = key.sign(digest, ec.ECDSA(Prehashed(algo)))  # DER ECDSA-Sig-Value
    else:
        sig = key.sign(digest, padding.PKCS1v15(), Prehashed(algo))
    return b64(sig)


def make_blank_pdf() -> bytes:
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << >> >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.7\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n%s\nendobj\n" % (i, body))
    xref_pos = out.tell()
    out.write(b"xref\n0 %d\n" % (len(objs) + 1))
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
              % (len(objs) + 1, xref_pos))
    return out.getvalue()


def make_xml() -> bytes:
    return b'<?xml version="1.0" encoding="UTF-8"?><invoice id="E2E-1"><amount>100</amount></invoice>'


# --- structural inspection of signed bytes (beyond the server's own /validate) ---

def read_dss(pdf_bytes: bytes):
    """(n_certs, n_ocsps, n_crls) from the PDF's Document Security Store, or None."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation.dss import DocumentSecurityStore

    reader = PdfFileReader(io.BytesIO(pdf_bytes))
    try:
        dss = DocumentSecurityStore.read_dss(reader)
    except Exception:
        return None
    return (len(dss.certs), len(dss.ocsps), len(dss.crls))


CCA_REVINFO_OID = "1.2.840.113583.1.1.8"


def has_cca_revinfo(pdf_bytes: bytes) -> bool:
    """True if any signature carries the Adobe pdfRevocationInfoArchival attr."""
    from pyhanko.pdf_utils.reader import PdfFileReader

    reader = PdfFileReader(io.BytesIO(pdf_bytes))
    for sig in reader.embedded_signatures:
        signed_attrs = sig.signer_info["signed_attrs"]
        for attr in signed_attrs:
            if attr["type"].dotted == CCA_REVINFO_OID:
                return True
    return False


def has_signature_timestamp(pdf_bytes: bytes) -> bool:
    """True if the first signature carries an RFC 3161 signature timestamp."""
    from pyhanko.pdf_utils.reader import PdfFileReader

    reader = PdfFileReader(io.BytesIO(pdf_bytes))
    for sig in reader.embedded_signatures:
        unsigned = sig.signer_info["unsigned_attrs"]
        if unsigned is None:
            continue
        for attr in unsigned:
            # id-aa-timeStampToken
            if attr["type"].dotted == "1.2.840.113549.1.9.16.2.14":
                return True
    return False
