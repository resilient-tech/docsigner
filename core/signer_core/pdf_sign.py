"""Interrupted PDF signing sessions.

start() prepares the PDF, builds the CMS signed attributes, and returns the
digest a token must sign. complete() takes the raw signature bytes and embeds
the finished CMS. The state in between is a plain dataclass that survives a
trip to disk, so the two calls can happen in different processes.

The pyHanko call sequence mirrors spike/spike_interrupted_signing.py, with
use_pades=True for production PAdES output. Shared CMS bricks live in cms.py.
"""

import asyncio
import base64
import dataclasses
import hashlib
import io
import secrets
from dataclasses import replace
from datetime import datetime, timezone

from asn1crypto import cms
from asn1crypto import x509 as asn1_x509
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers
from pyhanko.sign.ades.api import CAdESSignedAttrSpec
from pyhanko.sign.signers.pdf_byterange import PreparedByteRangeDigest
from pyhanko.sign.signers.pdf_cms import ExternalSigner, PdfCMSSignedAttributes, Signer
from pyhanko.sign.signers.pdf_signer import PdfTBSDocument
from pyhanko_certvalidator import CertificateValidator
from pyhanko_certvalidator.registry import SimpleCertificateStore

from .appearance import build_appearance, cert_common_name
from .policies import resolve_policy
from .cms import (
    PLACEHOLDER_SIG_SIZE,
    decode_state,
    encode_state,
    parse_cert,
    verify_signature,
)
from .errors import SignerError
from .ltv import _select_revinfo, async_augment, dss_from_embedded_revinfo
from .profiles import Profile, build_metadata, check_requirements, parse_digest_algorithm

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
    # TSA chosen at start; complete() must timestamp with the same authority.
    tsa_url: str = ""
    # Kept for the audit record in the complete response; default keeps
    # sessions serialized before this field loadable.
    field_name: str = ""
    # CCA profiles only: base64 DER of the signer's chain, gathered at start().
    # The CMS carries just the signer, so complete() needs these to build a
    # complete DSS mirror. Default keeps older serialized sessions loadable.
    chain_certs: list = dataclasses.field(default_factory=list)

    def to_bytes(self) -> bytes:
        return encode_state(self, _BYTES_FIELDS, kind="pdf")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "SessionState":
        return cls(**decode_state(raw, _BYTES_FIELDS, kind="pdf"))


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
        strict_ltv: bool = True,
        policy_dir=None,
    ) -> tuple[SessionState, bytes, str]:
        """Prepare a PDF for signing.

        Returns (session_state, to_sign_hash, digest_algorithm). The hash is
        the digest of the CMS signed attributes, ready for a raw PKCS#1 v1.5
        or ECDSA signature. ``strict_ltv`` keeps every gathered CRL so the
        revocation embedded for CCA profiles verifies offline; see ltv.py.
        ``policy_dir`` holds the artifacts for ``options.policy``; see
        policies.py.
        """
        return asyncio.run(
            _start(pdf_bytes, cert_der, options or {}, timestamper,
                   validation_context, strict_ltv, policy_dir)
        )

    @staticmethod
    def complete(
        state: SessionState,
        signature: bytes,
        *,
        timestamper=None,
        validation_context=None,
        strict_ltv: bool = True,
    ) -> bytes:
        """Embed the signature produced by the token; returns the signed PDF.

        B-LT and B-LTA sessions also need a validation context here: after
        the signature lands, revocation data is written to the DSS and (for
        B-LTA) an archive timestamp is appended. See ltv.py. ``strict_ltv``
        controls whether CRLs the chain needs are kept in the DSS.
        """
        return asyncio.run(
            _complete(state, signature, timestamper, validation_context, strict_ltv)
        )


async def _start(pdf_bytes, cert_der, options, timestamper, validation_context,
                 strict_ltv=True, policy_dir=None):
    profile = Profile.parse(options.get("profile"))
    check_requirements(profile, timestamper, validation_context)
    # Resolved before any PDF work: an unknown policy name or a missing
    # artifact should fail on the request, not after the document is written.
    policy = resolve_policy(options.get("policy"), policy_dir)
    # B-LT/B-LTA prepare and embed as B-T: PAdES wants the signature timestamp
    # in place before LTV data, and the DSS write plus archive timestamp are
    # key-free incremental updates that complete() adds afterwards (ltv.py).
    prepare_profile = Profile.B_T if profile.needs_revocation_info else profile

    md_algorithm = parse_digest_algorithm(options)
    signer_cert = parse_cert(cert_der)
    try:
        # strict=False: real-world PDFs (govt/portal/scanner output) often carry
        # minor xref-stream quirks that strict mode rejects; lenient parsing signs
        # them. Tradeoff: pyHanko's strict xref-ambiguity checks are skipped.
        writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes), strict=False)
    except Exception:
        raise SignerError("DOCUMENT_INVALID", "document is not a readable PDF") from None

    field_name = options.get("field_name") or f"Signature-{secrets.token_hex(4)}"
    stamp_style, field_spec = build_appearance(
        options.get("appearance"), field_name, writer=writer,
        reason=options.get("reason"), signer_name=cert_common_name(signer_cert),
    )

    # CCA profiles (ESAIG 1.19): revocation for the signer chain, and the TSA
    # chain when timestamping, is a *signed* attribute, so it must be gathered
    # before the token signs. It also has to fit inside the signature
    # placeholder, so it is collected before the placeholder is sized: Indian
    # CA CRLs run to megabytes, far past pyHanko's default estimate.
    attr_settings = None
    bytes_reserved = None
    chain_certs_b64 = []
    if profile.is_cca:
        revinfo, chain_certs = await _gather_cca_revinfo(
            signer_cert,
            validation_context,
            timestamper if profile.needs_timestamp else None,
            strict_ltv,
        )
        chain_certs_b64 = [base64.b64encode(c.dump()).decode("ascii") for c in chain_certs]
        attr_settings = PdfCMSSignedAttributes(
            signing_time=datetime.now(timezone.utc), adobe_revinfo_attr=revinfo
        )
        # /Contents is hex-encoded (2 chars per byte); 32 KB of headroom covers
        # the CMS body, the signer certificate, and a CCA-LTA timestamp token.
        bytes_reserved = (len(revinfo.dump()) + 32_768) * 2

    if policy is not None:
        # The policy rides on the CAdES attribute spec, which PAdES and the CCA
        # profiles both carry. Non-CCA profiles have no attr_settings until
        # here, so signing_time is set to match what pyHanko would have done.
        base = attr_settings or PdfCMSSignedAttributes(
            signing_time=datetime.now(timezone.utc)
        )
        attr_settings = replace(
            base,
            cades_signed_attrs=CAdESSignedAttrSpec(signature_policy_identifier=policy),
        )

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
        use_pades=not profile.is_cca,
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
        tsa_url=getattr(timestamper, "url", "") or "",
        field_name=field_name,
        chain_certs=chain_certs_b64,
    )
    return state, to_sign_hash, md_algorithm


async def _gather_cca_revinfo(signer_cert, validation_context, timestamper, strict_ltv):
    """Collect chain revocation data into a RevocationInfoArchival value.

    Validating the signer (and, for CCA-LTA, the TSA) against a fetching
    context leaves the gathered OCSP responses and CRLs on the context; those
    become the pdfRevocationInfoArchival signed attribute per CCA ESAIG 1.19.

    ``strict_ltv`` keeps every gathered CRL so the attribute verifies offline
    (Adobe LTV). Off, ESAIG 1.19.3's OCSP preference wins and CRLs are dropped
    once OCSP covers the chain, keeping the signed attribute small.
    """
    paths = []
    try:
        validator = CertificateValidator(
            signer_cert, validation_context=validation_context
        )
        paths.append(await validator.async_validate_usage(set()))
        if timestamper is not None:
            async for ts_path in timestamper.validation_paths(validation_context):
                paths.append(ts_path)
    except Exception as exc:
        raise SignerError(
            "INTERNAL",
            f"could not collect revocation data for the signer chain: {exc}"
            " (check TRUST_DIR contents and OCSP/CRL reachability)",
        ) from None

    ocsps, crls = _select_revinfo(validation_context, paths, strict_ltv)
    revinfo = Signer.format_revinfo(ocsp_responses=ocsps, crls=crls)
    if revinfo is None:
        raise SignerError(
            "INTERNAL",
            "no OCSP response or CRL could be obtained for the signer chain;"
            " refusing to produce a CCA-LTV signature without revocation data",
        )
    return revinfo, _chain_certs(paths)


def _chain_certs(paths):
    """Every certificate across the validated paths, deduplicated by DER.

    complete() embeds these in the CCA DSS mirror so a reader can build the
    chain: the CMS holds only the signer and the OCSP bundles skip the sub-CA.
    """
    seen, chain = set(), []
    for path in paths:
        for cert in path:
            der = cert.dump()
            if der not in seen:
                seen.add(der)
                chain.append(cert)
    return chain


async def _complete(state, signature, timestamper, validation_context, strict_ltv=True):
    profile = Profile(state.profile)
    check_requirements(profile, timestamper, validation_context, stage="complete")

    signer_cert = parse_cert(state.cert_der)
    verify_signature(signer_cert, signature, state.signed_attrs_der, state.digest_algorithm)

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
            strict_ltv=strict_ltv,
        )
    elif profile.is_cca:
        # The signed pdfRevocationInfoArchival attribute satisfies CCA ESAIG,
        # but Adobe's "LTV enabled" badge reads the document security store.
        # Mirror that same revocation into a DSS (reusing what start() already
        # gathered, no re-fetch) so the file reads as LTV everywhere while
        # staying CCA-compliant. The chain from start() rides along so the DSS
        # can build the path the CMS alone cannot.
        extra_certs = [
            asn1_x509.Certificate.load(base64.b64decode(c)) for c in state.chain_certs
        ]
        signed_pdf = dss_from_embedded_revinfo(signed_pdf, extra_certs=extra_certs)
    return signed_pdf
