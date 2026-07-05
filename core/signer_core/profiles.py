"""PAdES baseline profiles and their pyHanko signing settings."""

import enum

from pyhanko.sign import signers
from pyhanko.sign.fields import SigSeedSubFilter

from .errors import SignerError

DIGEST_ALGORITHMS = ("sha256", "sha384", "sha512")


class Profile(enum.Enum):
    B_B = "B-B"
    B_T = "B-T"
    B_LT = "B-LT"
    B_LTA = "B-LTA"

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
        """B-T and up carry an RFC 3161 signature timestamp."""
        return self is not Profile.B_B

    @property
    def needs_revocation_info(self) -> bool:
        """B-LT and up embed revocation data (DSS)."""
        return self in (Profile.B_LT, Profile.B_LTA)


def check_requirements(profile: Profile, timestamper, validation_context) -> None:
    """Fail early with a clear message when the deployment cannot honour the profile."""
    if profile.needs_timestamp and timestamper is None:
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            f"profile {profile.value} requires an RFC 3161 timestamp authority;"
            " none is configured (set TSA_URL)",
        )
    if profile.needs_revocation_info and validation_context is None:
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            f"profile {profile.value} requires trust anchors to gather revocation"
            " data; none are configured (set TRUST_DIR)",
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
) -> signers.PdfSignatureMetadata:
    return signers.PdfSignatureMetadata(
        field_name=field_name,
        md_algorithm=parse_digest_algorithm(options),
        reason=options.get("reason"),
        location=options.get("location"),
        subfilter=SigSeedSubFilter.PADES,
        embed_validation_info=profile.needs_revocation_info,
        use_pades_lta=profile is Profile.B_LTA,
        validation_context=validation_context if profile.needs_revocation_info else None,
    )
