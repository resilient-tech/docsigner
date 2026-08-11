"""Signature policy identifiers, the attribute that makes a signature
"an ICP-Brasil signature" rather than a generic PAdES one.

ETSI baseline profiles (B-B and up) need no policy attribute, which is why
India and the EU work without this module. Brazil is different: ITI classifies
a signature as AD-RB, AD-RT, AD-RC or AD-RA only when the CMS carries a
`signature-policy-identifier` naming one of their published policies. Argentina
and a few other LatAm PKIs work the same way.

The attribute is an OID plus a digest of the policy document itself, so the
hash has to match the exact artifact ITI published. Hardcoding a digest here
would rot the day a policy is reissued, and a wrong one produces a signature
that every verifier rejects. So a policy is registered as a name, an OID, a
URI and the artifact's filename, and the digest is computed from the file on
disk at signing time. `POLICY_DIR` points at the folder holding them.

Adding a country's policy is a download plus one row in POLICIES.
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


# ICP-Brasil's PAdES policies, from ITI's DOC-ICP-15.03. The OIDs are stable and
# public; the artifacts are not shipped here because they are ITI's documents,
# and their digests are computed from whichever revision the deployment fetched.
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
    """Turn a client-supplied policy name into the CMS attribute value.

    None or empty means no policy attribute, which is every profile that does
    not need one. An unknown name raises rather than signing without the
    attribute: a caller who asked for AD-RB and silently got plain PAdES would
    only find out at the verifier.
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
    """Build the SignaturePolicyIdentifier: OID, digest of the artifact, URI."""
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
