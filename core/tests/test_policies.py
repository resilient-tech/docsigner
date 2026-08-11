"""Signature policy identifiers: the attribute ICP-Brasil grades signatures on.

The digest in the attribute has to be the digest of the policy artifact the
deployment actually holds, so these tests write a stand-in artifact and check
that its hash is what reaches the CMS.
"""

import hashlib
import io

import pytest
from helpers_core import sign_hash
from pyhanko.pdf_utils.reader import PdfFileReader

from signer_core import SignerError, SigningSession
from signer_core.policies import POLICIES, resolve_policy

POLICY_OID = "2.16.76.1.7.1.11.1.1"  # ICP-Brasil PAdES AD-RB
ARTIFACT = b"stand-in for ITI's published policy document"


@pytest.fixture
def policy_dir(tmp_path):
    (tmp_path / POLICIES["icp-brasil-ad-rb"].artifact).write_bytes(ARTIFACT)
    return str(tmp_path)


def test_identifier_carries_the_oid_uri_and_artifact_digest(policy_dir):
    identifier = resolve_policy("icp-brasil-ad-rb", policy_dir).native
    assert identifier["sig_policy_id"] == POLICY_OID
    assert identifier["sig_policy_hash"]["digest"] == hashlib.sha256(ARTIFACT).digest()
    assert identifier["sig_policy_hash"]["digest_algorithm"]["algorithm"] == "sha256"
    qualifier = identifier["sig_policy_qualifiers"][0]
    assert qualifier["sig_policy_qualifier_id"] == "sp_uri"
    assert qualifier["sig_qualifier"].startswith("http://politicas.icpbrasil.gov.br/")


def test_no_policy_asked_for_means_no_attribute(policy_dir):
    assert resolve_policy(None, policy_dir) is None
    assert resolve_policy("", policy_dir) is None
    # No POLICY_DIR is fine as long as nobody asked for a policy.
    assert resolve_policy(None, None) is None


def test_a_policy_that_cannot_be_honoured_fails_loudly(tmp_path):
    """Never sign without the attribute a caller asked for: they would only
    find out at the verifier, with a document already handed to someone."""
    for name, directory in [
        ("no-such-policy", str(tmp_path)),  # unknown name
        ("icp-brasil-ad-rb", str(tmp_path)),  # artifact not downloaded
        ("icp-brasil-ad-rb", None),  # POLICY_DIR unset
    ]:
        with pytest.raises(SignerError) as err:
            resolve_policy(name, directory)
        assert err.value.code == "PROFILE_UNSUPPORTED"


def test_the_attribute_reaches_the_signed_pdf(blank_pdf, signer, policy_dir):
    """End to end: a B-B signature asked for AD-RB comes out carrying it."""
    key, cert_der = signer
    state, to_sign_hash, _ = SigningSession.start(
        blank_pdf,
        cert_der,
        {"profile": "B-B", "policy": "icp-brasil-ad-rb"},
        policy_dir=policy_dir,
    )
    signed = SigningSession.complete(state, sign_hash(key, to_sign_hash))

    embedded = PdfFileReader(io.BytesIO(signed)).embedded_signatures[0]
    attrs = embedded.signer_info["signed_attrs"]
    policy_attrs = [a for a in attrs if a["type"].native == "signature_policy_identifier"]
    assert len(policy_attrs) == 1
    value = policy_attrs[0]["values"][0].native
    assert value["sig_policy_id"] == POLICY_OID
    assert value["sig_policy_hash"]["digest"] == hashlib.sha256(ARTIFACT).digest()


def test_signing_without_a_policy_adds_no_attribute(blank_pdf, signer):
    """The default stays a plain PAdES baseline signature."""
    key, cert_der = signer
    state, to_sign_hash, _ = SigningSession.start(blank_pdf, cert_der, {"profile": "B-B"})
    signed = SigningSession.complete(state, sign_hash(key, to_sign_hash))

    embedded = PdfFileReader(io.BytesIO(signed)).embedded_signatures[0]
    types = [a["type"].native for a in embedded.signer_info["signed_attrs"]]
    assert "signature_policy_identifier" not in types
