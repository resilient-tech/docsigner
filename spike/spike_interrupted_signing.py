"""Phase 0 spike: prove the split-signing flow works.

Simulates the production flow without any browser or token:
  1. "Server" prepares a PDF for signing and produces the digest of the
     CMS signed attributes (this is what goes to the browser).
  2. "Token" signs that digest with a plain RSA key held in memory
     (stand-in for PKCS#11; the byte-level contract is identical).
  3. "Server" assembles the CMS and embeds it in the PDF.
  4. pyHanko validates the result.

Run: python spike_interrupted_signing.py
"""

import asyncio
import datetime
import hashlib
import io

from asn1crypto import algos
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from pyhanko.keys.pemder import load_certs_from_pemder_data
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import signers
from pyhanko.sign.signers.pdf_cms import ExternalSigner
from pyhanko.sign.signers.pdf_signer import PdfTBSDocument
from pyhanko.sign.validation import async_validate_pdf_signature
from pyhanko_certvalidator import ValidationContext
from pyhanko_certvalidator.registry import SimpleCertificateStore

RSA_SIG_SIZE = 256  # 2048-bit key


def make_self_signed_cert():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Spike Signer"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DocSigner Spike"),
        ]
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return key, cert.public_bytes(serialization.Encoding.DER)


def make_blank_pdf() -> bytes:
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Resources << >> >>",
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
    out.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objs) + 1, xref_pos)
    )
    return out.getvalue()


async def main():
    key, cert_der = make_self_signed_cert()
    signer_cert = list(load_certs_from_pemder_data(cert_der))[0]

    pdf_bytes = make_blank_pdf()
    w = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes))

    # --- step 1: server side, prepare + digest -------------------------
    cert_store = SimpleCertificateStore()
    ext_signer = ExternalSigner(
        signing_cert=signer_cert,
        cert_registry=cert_store,
        signature_value=RSA_SIG_SIZE,
    )
    pdf_signer = signers.PdfSigner(
        signers.PdfSignatureMetadata(
            field_name="SpikeSignature", md_algorithm="sha256"
        ),
        signer=ext_signer,
    )
    prep_digest, tbs_document, output = (
        await pdf_signer.async_digest_doc_for_signing(w)
    )

    signed_attrs = await ext_signer.signed_attrs(
        prep_digest.document_digest, "sha256", use_pades=False
    )
    to_sign_hash = hashlib.sha256(signed_attrs.dump()).digest()
    print(f"to_sign_hash ({len(to_sign_hash)} bytes): {to_sign_hash.hex()}")

    # --- step 2: "token" side, sign the digest -------------------------
    # PKCS#11 CKM_RSA_PKCS on a DigestInfo == this Prehashed sign call.
    from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

    signature = key.sign(
        to_sign_hash, padding.PKCS1v15(), Prehashed(hashes.SHA256())
    )
    print(f"signature: {len(signature)} bytes")

    # --- step 3: server side, assemble CMS + embed ---------------------
    # a second ExternalSigner carrying the real signature value, fed the
    # SAME signed_attrs (so the signed bytes match exactly)
    final_signer = ExternalSigner(
        signing_cert=signer_cert,
        cert_registry=cert_store,
        signature_value=signature,
    )
    sig_cms = await final_signer.async_sign_prescribed_attributes(
        "sha256", signed_attrs=signed_attrs
    )

    await PdfTBSDocument.async_finish_signing(output, prep_digest, sig_cms)

    signed_pdf = output.getvalue()
    with open("spike_signed.pdf", "wb") as f:
        f.write(signed_pdf)

    # --- step 4: validate ----------------------------------------------
    r = PdfFileReader(io.BytesIO(signed_pdf))
    emb = r.embedded_signatures[0]
    vc = ValidationContext(trust_roots=list(load_certs_from_pemder_data(cert_der)))
    status = await async_validate_pdf_signature(emb, signer_validation_context=vc)
    print(status.pretty_print_details())
    assert status.intact and status.valid, "signature INVALID"
    print("\nSPIKE OK: intact + cryptographically valid")


if __name__ == "__main__":
    asyncio.run(main())
