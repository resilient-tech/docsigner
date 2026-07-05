import pytest

from signer_core import SignerError, validate


def test_unsigned_pdf_has_no_signatures(blank_pdf):
    assert validate(blank_pdf) == []


def test_garbage_document_is_rejected():
    with pytest.raises(SignerError) as err:
        validate(b"definitely not a pdf")
    assert err.value.code == "DOCUMENT_INVALID"
