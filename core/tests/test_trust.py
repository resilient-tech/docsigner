"""The trust directory loader and the TSA registry."""

import pytest
from cryptography.hazmat.primitives import serialization
from helpers_core import make_self_signed_cert

from signer_core import SignerError
from signer_core.trust import KNOWN_TSAS, load_trust_certs, resolve_tsa_url


def _pem(name):
    _, cert = make_self_signed_cert(name)
    return cert.public_bytes(serialization.Encoding.PEM)


def test_loader_recurses_and_skips_archive(tmp_path):
    (tmp_path / "in").mkdir()
    (tmp_path / "archive" / "in").mkdir(parents=True)
    (tmp_path / "in" / "active.pem").write_bytes(_pem("Active Root"))
    (tmp_path / "top-level.pem").write_bytes(_pem("Top Level"))
    (tmp_path / "archive" / "in" / "old.pem").write_bytes(_pem("Expired Root"))
    (tmp_path / "in" / "notes.txt").write_text("not a certificate")

    names = {c.subject.native["common_name"] for c in load_trust_certs(tmp_path)}
    assert names == {"Active Root", "Top Level"}


def test_resolve_tsa_by_name_default_and_unknown():
    assert resolve_tsa_url("digicert", "http://fallback") == KNOWN_TSAS["digicert"]
    assert resolve_tsa_url("", "http://fallback") == "http://fallback"
    with pytest.raises(SignerError) as err:
        resolve_tsa_url("notary-of-nowhere", "http://fallback")
    assert err.value.code == "PROFILE_UNSUPPORTED"
