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
from pyhanko.sign.signers.pdf_cms import ExternalSigner
from pyhanko.sign.signers.pdf_signer import PdfTBSDocument
from pyhanko_certvalidator.registry import SimpleCertificateStore

from .appearance import build_appearance
from .errors import SignerError
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
    def complete(state: SessionState, signature: bytes, *, timestamper=None) -> bytes:
        """Embed the signature produced by the token; returns the signed PDF."""
        return asyncio.run(_complete(state, signature, timestamper))


async def _start(pdf_bytes, cert_der, options, timestamper, validation_context):
    profile = Profile.parse(options.get("profile"))
    check_requirements(profile, timestamper, validation_context)
    if profile.needs_revocation_info:
        # ponytail: LT/LTA need pyHanko's PostSignInstructions carried across the
        # start/complete gap, which is not serializable yet; server-side signing
        # covers those profiles today
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            f"profile {profile.value} is not available for token sessions yet;"
            " use server-side signing",
        )

    md_algorithm = parse_digest_algorithm(options)
    signer_cert = _parse_cert(cert_der)
    try:
        writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes))
    except Exception:
        raise SignerError("DOCUMENT_INVALID", "document is not a readable PDF") from None

    field_name = options.get("field_name") or f"Signature-{secrets.token_hex(4)}"
    stamp_style, field_spec = build_appearance(options.get("appearance"), field_name)

    placeholder_signer = ExternalSigner(
        signing_cert=signer_cert,
        cert_registry=SimpleCertificateStore(),
        signature_value=PLACEHOLDER_SIG_SIZE,
    )
    pdf_signer = signers.PdfSigner(
        build_metadata(options, profile, field_name, validation_context),
        signer=placeholder_signer,
        timestamper=timestamper if profile.needs_timestamp else None,
        stamp_style=stamp_style,
        new_field_spec=field_spec,
    )
    try:
        prep_digest, _tbs_document, output = (
            await pdf_signer.async_digest_doc_for_signing(writer)
        )
    except SignerError:
        raise
    except Exception as exc:
        raise SignerError(
            "DOCUMENT_INVALID", f"could not prepare the PDF for signing: {exc}"
        ) from None

    signed_attrs = await placeholder_signer.signed_attrs(
        prep_digest.document_digest, md_algorithm, use_pades=True
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


async def _complete(state, signature, timestamper):
    profile = Profile(state.profile)
    if profile.needs_timestamp and timestamper is None:
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            f"profile {profile.value} requires an RFC 3161 timestamp authority"
            " at completion; none is configured (set TSA_URL)",
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
    return output.getvalue()


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
