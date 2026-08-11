"""PAdES baseline profiles and their pyHanko signing settings."""

import enum

from pyhanko.sign import signers
from pyhanko.sign.ades.api import CAdESSignedAttrSpec
from pyhanko.sign.fields import SigSeedSubFilter

from .errors import SignerError

DIGEST_ALGORITHMS = ("sha256", "sha384", "sha512")


class Profile(enum.Enum):
    B_B = "B-B"
    B_T = "B-T"
    B_LT = "B-LT"
    B_LTA = "B-LTA"
    # CCA India ESAIG section 1.19/1.25: PKCS#7 signature with the chain and
    # revocation info carried as the pdfRevocationInfoArchival signed attribute
    # (OID 1.2.840.113583.1.1.8) instead of a PAdES DSS. CCA-LTA adds an
    # RFC 3161 signature timestamp on top of CCA-LTV.
    CCA_LTV = "CCA-LTV"
    CCA_LTA = "CCA-LTA"

    @classmethod
    def parse(cls, value) -> "Profile":
        if not value:
            return cls.B_B
        try:
            return cls(value)
        except ValueError:
            raise SignerError(
                "PROFILE_UNSUPPORTED",
                f"unknown profile {value!r}; expected one of "
                + ", ".join(p.value for p in cls),
            ) from None

    @property
    def needs_timestamp(self) -> bool:
        """Profiles that carry an RFC 3161 signature timestamp."""
        return self in (Profile.B_T, Profile.B_LT, Profile.B_LTA, Profile.CCA_LTA)

    @property
    def needs_revocation_info(self) -> bool:
        """B-LT and up embed revocation data (DSS)."""
        return self in (Profile.B_LT, Profile.B_LTA)

    @property
    def is_cca(self) -> bool:
        """CCA profiles embed revocation as the pdfRevocationInfoArchival signed attribute."""
        return self in (Profile.CCA_LTV, Profile.CCA_LTA)


def check_requirements(profile: Profile, timestamper, validation_context, *,
                       stage: str = "start") -> None:
    """Fail early when the deployment cannot honour the profile.

    Called at both ends of a token round trip. stage="complete" only tunes the
    wording; a CCA chain is gathered at start, so its trust dir is checked
    there, not again at completion.
    """
    suffix = " at completion" if stage == "complete" else ""
    if profile.needs_timestamp and timestamper is None:
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            f"profile {profile.value} requires an RFC 3161 timestamp authority{suffix};"
            " none is configured (set TSA_URL)",
        )
    needs_trust = profile.needs_revocation_info or (profile.is_cca and stage == "start")
    if needs_trust and validation_context is None:
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            f"profile {profile.value} requires trust anchors to gather revocation"
            f" data{suffix}; none are configured (set TRUST_DIR)",
        )


def parse_digest_algorithm(options: dict) -> str:
    md = (options.get("digest_algorithm") or "sha256").lower()
    if md not in DIGEST_ALGORITHMS:
        raise SignerError(
            "DOCUMENT_INVALID",
            "digest_algorithm must be one of " + ", ".join(DIGEST_ALGORITHMS),
        )
    return md


def build_metadata(
    options: dict,
    profile: Profile,
    field_name: str,
    validation_context=None,
    policy=None,
) -> signers.PdfSignatureMetadata:
    # CCA profiles use the plain PKCS#7 subfilter; pyHanko then routes embedded
    # validation info into the pdfRevocationInfoArchival signed attribute rather
    # than a DSS. The token flow gathers that attribute itself (pdf_sign.py), so
    # it builds metadata without a validation context.
    if profile.is_cca:
        subfilter = SigSeedSubFilter.ADOBE_PKCS7_DETACHED
        embed = validation_context is not None
    else:
        subfilter = SigSeedSubFilter.PADES
        embed = profile.needs_revocation_info
    return signers.PdfSignatureMetadata(
        field_name=field_name,
        md_algorithm=parse_digest_algorithm(options),
        reason=options.get("reason"),
        location=options.get("location"),
        subfilter=subfilter,
        embed_validation_info=embed,
        use_pades_lta=profile is Profile.B_LTA,
        validation_context=validation_context if embed else None,
        # Only set when a policy was asked for: pyHanko emits the CAdES
        # attribute block whenever a spec is present, and an empty one on a
        # plain PAdES signature is noise a verifier has to skip past.
        cades_signed_attr_spec=(
            CAdESSignedAttrSpec(signature_policy_identifier=policy) if policy else None
        ),
    )
