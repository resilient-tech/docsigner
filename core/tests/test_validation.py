import io

import pytest
from helpers_core import sign_hash
from pyhanko.pdf_utils import generic
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

from docsigner_core import SignerError, SigningSession, validate


def test_unsigned_pdf_has_no_signatures(blank_pdf):
    assert validate(blank_pdf) == []


def test_disallowed_change_after_signing_is_flagged(signer, blank_pdf):
    """A content edit after signing flips modifications_ok, intact stays true.

    The signed byte range is untouched, so intact/valid still hold; the
    structured flag is what tells a caller the document was altered afterwards.
    """
    key, cert_der = signer
    state, to_sign_hash, _ = SigningSession.start(blank_pdf, cert_der, {"profile": "B-B"})
    signed_pdf = SigningSession.complete(state, sign_hash(key, to_sign_hash))

    r = validate(signed_pdf)[0]
    assert r["modifications_ok"] is True

    tampered = io.BytesIO(signed_pdf)
    writer = IncrementalPdfFileWriter(tampered, strict=False)
    writer.root["/Tampered"] = generic.BooleanObject(True)
    writer.update_root()
    writer.write_in_place()

    r = validate(tampered.getvalue())[0]
    assert r["intact"] is True
    assert r["valid"] is True
    assert r["modifications_ok"] is False


def test_garbage_document_is_rejected():
    with pytest.raises(SignerError) as err:
        validate(b"definitely not a pdf")
    assert err.value.code == "DOCUMENT_INVALID"
