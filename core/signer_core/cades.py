"""Detached CAdES signatures over arbitrary files (CMS SignedData, .p7s).

Same interrupted two-step dance as session.py, minus the PDF machinery: the
signed attributes cover the file's digest, a token signs their hash, and the
finished CMS ships as a detached .p7s. Profiles stop at B-T (CAdES-BES plus an
RFC 3161 signature timestamp); the long-term CAdES archival forms are a
different standard ladder and stay out until someone needs them.
"""

import asyncio
import dataclasses
import hashlib
from datetime import datetime, timezone

from asn1crypto import cms
from pyhanko.sign.ades.api import CAdESSignedAttrSpec
from pyhanko.sign.signers.pdf_cms import ExternalSigner, PdfCMSSignedAttributes
from pyhanko_certvalidator.registry import SimpleCertificateStore

from .errors import SignerError
from .profiles import Profile, parse_digest_algorithm
from .server_signer import _load_p12_signer
from .session import (
    PLACEHOLDER_SIG_SIZE,
    _decode_state,
    _encode_state,
    _parse_cert,
    _verify_signature,
)

_CADES_PROFILES = (Profile.B_B, Profile.B_T)

_BYTES_FIELDS = ("signed_attrs_der", "cert_der")


@dataclasses.dataclass
class CadesState:
    """Everything needed to assemble the CMS once the hash comes back signed."""

    signed_attrs_der: bytes
    cert_der: bytes
    digest_algorithm: str
    profile: str
    tsa_url: str = ""

    def to_bytes(self) -> bytes:
        return _encode_state(self, _BYTES_FIELDS, kind="cades")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "CadesState":
        return cls(**_decode_state(raw, _BYTES_FIELDS, kind="cades"))


def _check_profile(options) -> Profile:
    profile = Profile.parse(options.get("profile"))
    if profile not in _CADES_PROFILES:
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            f"CAdES supports {', '.join(p.value for p in _CADES_PROFILES)};"
            f" got {profile.value}",
        )
    return profile


class CadesSession:
    """The two halves of a token CAdES round trip."""

    @staticmethod
    def start(
        data: bytes, cert_der: bytes, options: dict | None = None, *, timestamper=None
    ) -> tuple[CadesState, bytes, str]:
        return asyncio.run(_start(data, cert_der, options or {}, timestamper))

    @staticmethod
    def complete(state: CadesState, signature: bytes, *, timestamper=None) -> bytes:
        return asyncio.run(_complete(state, signature, timestamper))


async def _start(data, cert_der, options, timestamper):
    profile = _check_profile(options)
    if profile.needs_timestamp and timestamper is None:
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            "profile B-T requires an RFC 3161 timestamp authority (set TSA_URL)",
        )
    md_algorithm = parse_digest_algorithm(options)
    signer_cert = _parse_cert(cert_der)

    placeholder = ExternalSigner(
        signing_cert=signer_cert,
        cert_registry=SimpleCertificateStore(),
        signature_value=PLACEHOLDER_SIG_SIZE,
    )
    signed_attrs = await placeholder.signed_attrs(
        hashlib.new(md_algorithm, data).digest(),
        md_algorithm,
        attr_settings=PdfCMSSignedAttributes(
            signing_time=datetime.now(timezone.utc),
            cades_signed_attrs=CAdESSignedAttrSpec(),
        ),
        use_pades=False,
        is_pdf_sig=False,
    )
    signed_attrs_der = signed_attrs.dump()
    state = CadesState(
        signed_attrs_der=signed_attrs_der,
        cert_der=cert_der,
        digest_algorithm=md_algorithm,
        profile=profile.value,
        tsa_url=getattr(timestamper, "url", "") or "",
    )
    return state, hashlib.new(md_algorithm, signed_attrs_der).digest(), md_algorithm


async def _complete(state, signature, timestamper):
    profile = Profile(state.profile)
    if profile.needs_timestamp and timestamper is None:
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            "profile B-T requires an RFC 3161 timestamp authority at completion",
        )
    signer_cert = _parse_cert(state.cert_der)
    _verify_signature(signer_cert, signature, state.signed_attrs_der, state.digest_algorithm)

    final_signer = ExternalSigner(
        signing_cert=signer_cert,
        cert_registry=SimpleCertificateStore(),
        signature_value=signature,
    )
    signature_cms = await final_signer.async_sign_prescribed_attributes(
        state.digest_algorithm,
        signed_attrs=cms.CMSAttributes.load(state.signed_attrs_der),
        timestamper=timestamper if profile.needs_timestamp else None,
    )
    return signature_cms.dump()


def sign_cades_with_p12(data, p12_path, passphrase, options, *, timestamper=None) -> bytes:
    """One-shot detached CAdES with the server-held key."""
    profile = _check_profile(options or {})
    md_algorithm = parse_digest_algorithm(options or {})
    signer = _load_p12_signer(p12_path, passphrase)
    signature_cms = signer.sign_general_data(
        data,
        md_algorithm,
        detached=True,
        timestamper=timestamper if profile.needs_timestamp else None,
        use_cades=True,
        cades_signed_attr_meta=CAdESSignedAttrSpec(),
    )
    return signature_cms.dump()
