"""The stamp that says "this is a Brazilian signature", not just any signature.

Most countries grade a signature by its profile (B-B, B-T and up), so they never
come here. Brazil grades it by a named policy the signature has to point at.

A policy is an ID plus a hash of the policy document. We hash the file on disk
at signing time rather than hardcode it, because a reissued document with a
stale hash makes every verifier reject the signature. POLICY_DIR holds the files.

Adding a country: download its document, add one row to POLICIES.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from asn1crypto import algos
from pyhanko.sign.ades.api import SignaturePolicyIdentifier
from pyhanko.sign.ades.cades_asn1 import (
    SigPolicyQualifierInfo,
    SigPolicyQualifierInfos,
    SignaturePolicyId,
)

from .errors import SignerError


@dataclass(frozen=True)
class SignaturePolicy:
    """One published policy: what to claim, and which file proves the claim."""

    oid: str
    uri: str
    artifact: str
    digest_algorithm: str = "sha256"


# Brazil's four, from ITI's DOC-ICP-15.03. The IDs are public and stable. The
# documents are ITI's, so we do not ship them; the deployment fetches its own.
POLICIES = {
    "icp-brasil-ad-rb": SignaturePolicy(
        oid="2.16.76.1.7.1.11.1.1",
        uri="http://politicas.icpbrasil.gov.br/PA_PAdES_AD_RB_v1_1.der",
        artifact="PA_PAdES_AD_RB_v1_1.der",
    ),
    "icp-brasil-ad-rt": SignaturePolicy(
        oid="2.16.76.1.7.1.12.1.1",
        uri="http://politicas.icpbrasil.gov.br/PA_PAdES_AD_RT_v1_1.der",
        artifact="PA_PAdES_AD_RT_v1_1.der",
    ),
    "icp-brasil-ad-rc": SignaturePolicy(
        oid="2.16.76.1.7.1.13.1.1",
        uri="http://politicas.icpbrasil.gov.br/PA_PAdES_AD_RC_v1_1.der",
        artifact="PA_PAdES_AD_RC_v1_1.der",
    ),
    "icp-brasil-ad-ra": SignaturePolicy(
        oid="2.16.76.1.7.1.14.1.1",
        uri="http://politicas.icpbrasil.gov.br/PA_PAdES_AD_RA_v1_1.der",
        artifact="PA_PAdES_AD_RA_v1_1.der",
    ),
}


def resolve_policy(name, policy_dir=None):
    """Policy name to the thing that goes in the signature. Empty means none.

    An unknown name raises. Someone who asked for a Brazilian signature and
    quietly got a plain one would only find out at the verifier.
    """
    if not name:
        return None
    try:
        policy = POLICIES[name]
    except KeyError:
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            f"unknown signature policy {name!r}; expected one of "
            + ", ".join(sorted(POLICIES)),
        ) from None

    if not policy_dir:
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            f"signature policy {name!r} needs POLICY_DIR set to the folder "
            f"holding {policy.artifact} (download it from {policy.uri})",
        )
    path = Path(policy_dir) / policy.artifact
    try:
        artifact = path.read_bytes()
    except OSError:
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            f"signature policy {name!r} needs {path}; download it from {policy.uri}",
        ) from None

    return _identifier(policy, artifact)


def _identifier(policy, artifact):
    """The ID, the hash of the policy document, and where to find it."""
    digest = hashlib.new(policy.digest_algorithm, artifact).digest()
    return SignaturePolicyIdentifier(
        name="signature_policy_id",
        value=SignaturePolicyId(
            {
                "sig_policy_id": policy.oid,
                "sig_policy_hash": algos.DigestInfo(
                    {
                        "digest_algorithm": {"algorithm": policy.digest_algorithm},
                        "digest": digest,
                    }
                ),
                "sig_policy_qualifiers": SigPolicyQualifierInfos(
                    [
                        SigPolicyQualifierInfo(
                            {
                                "sig_policy_qualifier_id": "sp_uri",
                                "sig_qualifier": policy.uri,
                            }
                        )
                    ]
                ),
            }
        ),
    )
