"""Interrupted signing sessions.

start() prepares the PDF, builds the CMS signed attributes, and returns the
digest a token must sign. complete() takes the raw signature bytes and embeds
the finished CMS. The state in between is a plain dataclass that survives a
trip to disk, so the two calls can happen in different processes.

The pyHanko call sequence mirrors spike/spike_interrupted_signing.py, with
use_pades=True for production PAdES output.
"""

import asyncio
import base64
import dataclasses
import hashlib
import io
import json
import secrets
from datetime import datetime, timezone

from asn1crypto import cms
from asn1crypto import x509 as asn1_x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from cryptography.hazmat.primitives.serialization import load_der_public_key
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers
from pyhanko.sign.signers.pdf_byterange import PreparedByteRangeDigest
from pyhanko.sign.signers.pdf_cms import ExternalSigner, PdfCMSSignedAttributes, Signer
from pyhanko.sign.signers.pdf_signer import PdfTBSDocument
from pyhanko_certvalidator import CertificateValidator
from pyhanko_certvalidator.registry import SimpleCertificateStore

from .appearance import build_appearance
from .errors import SignerError
from .ltv import _ocsp_good_serials, _serials_below_anchor, async_augment
from .profiles import Profile, build_metadata, check_requirements, parse_digest_algorithm

# Placeholder for the yet-unknown signature value; fits RSA-4096.
PLACEHOLDER_SIG_SIZE = 512

_HASH_CLASSES = {
    "sha256": hashes.SHA256,
    "sha384": hashes.SHA384,
    "sha512": hashes.SHA512,
}

_BYTES_FIELDS = ("prepared_pdf", "document_digest", "signed_attrs_der", "cert_der")


@dataclasses.dataclass
class SessionState:
    """Everything needed to resume signing once the hash comes back signed."""

    prepared_pdf: bytes
    document_digest: bytes
    reserved_region_start: int
    reserved_region_end: int
    signed_attrs_der: bytes
    cert_der: bytes
    digest_algorithm: str
    profile: str

    def to_bytes(self) -> bytes:
        data = dataclasses.asdict(self)
        for field in _BYTES_FIELDS:
            data[field] = base64.b64encode(data[field]).decode("ascii")
        return json.dumps(data).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "SessionState":
        data = json.loads(raw.decode("utf-8"))
        for field in _BYTES_FIELDS:
            data[field] = base64.b64decode(data[field])
        return cls(**data)


class SigningSession:
    """The two halves of a token signing round trip."""

    @staticmethod
    def start(
        pdf_bytes: bytes,
        cert_der: bytes,
        options: dict | None = None,
        *,
        timestamper=None,
        validation_context=None,
    ) -> tuple[SessionState, bytes, str]:
        """Prepare a PDF for signing.

        Returns (session_state, to_sign_hash, digest_algorithm). The hash is
        the digest of the CMS signed attributes, ready for a raw PKCS#1 v1.5
        or ECDSA signature.
        """
        return asyncio.run(
            _start(pdf_bytes, cert_der, options or {}, timestamper, validation_context)
        )

    @staticmethod
    def complete(
        state: SessionState,
        signature: bytes,
        *,
        timestamper=None,
        validation_context=None,
    ) -> bytes:
        """Embed the signature produced by the token; returns the signed PDF.

        B-LT and B-LTA sessions also need a validation context here: after
        the signature lands, revocation data is written to the DSS and (for
        B-LTA) an archive timestamp is appended. See ltv.py.
        """
        return asyncio.run(_complete(state, signature, timestamper, validation_context))


async def _start(pdf_bytes, cert_der, options, timestamper, validation_context):
    profile = Profile.parse(options.get("profile"))
    check_requirements(profile, timestamper, validation_context)
    # B-LT/B-LTA prepare and embed as B-T: PAdES wants the signature timestamp
    # in place before LTV data, and the DSS write plus archive timestamp are
    # key-free incremental updates that complete() adds afterwards (ltv.py).
    prepare_profile = Profile.B_T if profile.needs_revocation_info else profile

    md_algorithm = parse_digest_algorithm(options)
    signer_cert = _parse_cert(cert_der)
    try:
        # strict=False: real-world PDFs (govt/portal/scanner output) often carry
        # minor xref-stream quirks that strict mode rejects; lenient parsing signs
        # them. Tradeoff: pyHanko's strict xref-ambiguity checks are skipped.
        writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes), strict=False)
    except Exception:
        raise SignerError("DOCUMENT_INVALID", "document is not a readable PDF") from None

    field_name = options.get("field_name") or f"Signature-{secrets.token_hex(4)}"
    stamp_style, field_spec = build_appearance(options.get("appearance"), field_name)

    # CCA profiles (ESAIG 1.19): revocation for the signer chain, and the TSA
    # chain when timestamping, is a *signed* attribute, so it must be gathered
    # before the token signs. It also has to fit inside the signature
    # placeholder, so it is collected before the placeholder is sized: Indian
    # CA CRLs run to megabytes, far past pyHanko's default estimate.
    attr_settings = None
    bytes_reserved = None
    if profile.adobe_revinfo:
        revinfo = await _gather_adobe_revinfo(
            signer_cert,
            validation_context,
            timestamper if profile.needs_timestamp else None,
        )
        attr_settings = PdfCMSSignedAttributes(
            signing_time=datetime.now(timezone.utc), adobe_revinfo_attr=revinfo
        )
        # /Contents is hex-encoded (2 chars per byte); 32 KB of headroom covers
        # the CMS body, the signer certificate, and a CCA-LTA timestamp token.
        bytes_reserved = (len(revinfo.dump()) + 32_768) * 2

    placeholder_signer = ExternalSigner(
        signing_cert=signer_cert,
        cert_registry=SimpleCertificateStore(),
        signature_value=PLACEHOLDER_SIG_SIZE,
    )
    pdf_signer = signers.PdfSigner(
        build_metadata(options, prepare_profile, field_name),
        signer=placeholder_signer,
        timestamper=timestamper if profile.needs_timestamp else None,
        stamp_style=stamp_style,
        new_field_spec=field_spec,
    )
    try:
        prep_digest, _tbs_document, output = (
            await pdf_signer.async_digest_doc_for_signing(
                writer, bytes_reserved=bytes_reserved
            )
        )
    except SignerError:
        raise
    except Exception as exc:
        raise SignerError(
            "DOCUMENT_INVALID", f"could not prepare the PDF for signing: {exc}"
        ) from None

    signed_attrs = await placeholder_signer.signed_attrs(
        prep_digest.document_digest,
        md_algorithm,
        attr_settings=attr_settings,
        use_pades=not profile.adobe_revinfo,
    )
    signed_attrs_der = signed_attrs.dump()
    to_sign_hash = hashlib.new(md_algorithm, signed_attrs_der).digest()

    state = SessionState(
        prepared_pdf=output.getvalue(),
        document_digest=prep_digest.document_digest,
        reserved_region_start=prep_digest.reserved_region_start,
        reserved_region_end=prep_digest.reserved_region_end,
        signed_attrs_der=signed_attrs_der,
        cert_der=cert_der,
        digest_algorithm=md_algorithm,
        profile=profile.value,
    )
    return state, to_sign_hash, md_algorithm


async def _gather_adobe_revinfo(signer_cert, validation_context, timestamper):
    """Collect chain revocation data into a RevocationInfoArchival value.

    Validating the signer (and, for CCA-LTA, the TSA) against a fetching
    context leaves the gathered OCSP responses and CRLs on the context; those
    become the pdfRevocationInfoArchival signed attribute per CCA ESAIG 1.19.
    """
    needs_revinfo = set()
    try:
        validator = CertificateValidator(
            signer_cert, validation_context=validation_context
        )
        path = await validator.async_validate_usage(set())
        needs_revinfo.update(_serials_below_anchor(path))
        if timestamper is not None:
            async for ts_path in timestamper.validation_paths(validation_context):
                needs_revinfo.update(_serials_below_anchor(ts_path))
    except Exception as exc:
        raise SignerError(
            "INTERNAL",
            f"could not collect revocation data for the signer chain: {exc}"
            " (check TRUST_DIR contents and OCSP/CRL reachability)",
        ) from None

    ocsps = list(validation_context.ocsps)
    crls = list(validation_context.crls)
    # The fetcher collects both sources; CRLs from Indian CAs run to megabytes
    # while the OCSP responses total a few KB. ESAIG 1.19.3 prefers OCSP, so
    # drop the CRLs whenever every chain certificate below its trust anchor is
    # covered by a good OCSP response.
    if ocsps and crls and needs_revinfo <= _ocsp_good_serials(ocsps):
        crls = []

    revinfo = Signer.format_revinfo(ocsp_responses=ocsps, crls=crls)
    if revinfo is None:
        raise SignerError(
            "INTERNAL",
            "no OCSP response or CRL could be obtained for the signer chain;"
            " refusing to produce a CCA-LTV signature without revocation data",
        )
    return revinfo


async def _complete(state, signature, timestamper, validation_context):
    profile = Profile(state.profile)
    if profile.needs_timestamp and timestamper is None:
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            f"profile {profile.value} requires an RFC 3161 timestamp authority"
            " at completion; none is configured (set TSA_URL)",
        )
    if profile.needs_revocation_info and validation_context is None:
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            f"profile {profile.value} requires trust anchors to gather revocation"
            " data at completion; none are configured (set TRUST_DIR)",
        )

    signer_cert = _parse_cert(state.cert_der)
    _verify_signature(signer_cert, signature, state.signed_attrs_der, state.digest_algorithm)

    # Feed back the exact signed attributes from start(), so the bytes the
    # token signed are the bytes that land in the CMS.
    signed_attrs = cms.CMSAttributes.load(state.signed_attrs_der)
    final_signer = ExternalSigner(
        signing_cert=signer_cert,
        cert_registry=SimpleCertificateStore(),
        signature_value=signature,
    )
    signature_cms = await final_signer.async_sign_prescribed_attributes(
        state.digest_algorithm,
        signed_attrs=signed_attrs,
        timestamper=timestamper if profile.needs_timestamp else None,
    )

    output = io.BytesIO(state.prepared_pdf)
    prep_digest = PreparedByteRangeDigest(
        document_digest=state.document_digest,
        reserved_region_start=state.reserved_region_start,
        reserved_region_end=state.reserved_region_end,
    )
    await PdfTBSDocument.async_finish_signing(output, prep_digest, signature_cms)
    signed_pdf = output.getvalue()

    if profile.needs_revocation_info:
        signed_pdf = await async_augment(
            signed_pdf,
            validation_context,
            timestamper=timestamper,
            archive_timestamp=profile is Profile.B_LTA,
            md_algorithm=state.digest_algorithm,
        )
    return signed_pdf


def _parse_cert(cert_der: bytes) -> asn1_x509.Certificate:
    try:
        cert = asn1_x509.Certificate.load(cert_der)
        key_algorithm = cert.public_key.algorithm
    except Exception:
        raise SignerError("CERT_INVALID", "certificate is not valid DER") from None
    if key_algorithm not in ("rsa", "ec"):
        raise SignerError(
            "CERT_INVALID",
            f"unsupported key type {key_algorithm!r}; RSA and EC are supported",
        )
    return cert


def _verify_signature(signer_cert, signature, signed_attrs_der, md_algorithm):
    """Reject garbage before it gets baked into the PDF."""
    public_key = load_der_public_key(signer_cert.public_key.dump())
    digest = hashlib.new(md_algorithm, signed_attrs_der).digest()
    prehashed = Prehashed(_HASH_CLASSES[md_algorithm]())
    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(signature, digest, padding.PKCS1v15(), prehashed)
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, digest, ec.ECDSA(prehashed))
        else:
            raise SignerError("CERT_INVALID", "unsupported key type")
    except InvalidSignature:
        raise SignerError(
            "SIGNATURE_INVALID",
            "signature does not verify against the supplied certificate",
        ) from None
