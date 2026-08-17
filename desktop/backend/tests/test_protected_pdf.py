"""A password-protected PDF is refused in words a person can read.

pdfium says "Failed to load document (PDFium: Incorrect password error)", which
reached the window verbatim and sat above the *previous* file's preview.

Both readers go through rendering._open, so this covers the preview and the
signing run at once — signing.py surfaces `.message` the same way.

Lives here rather than in core/tests because rasterization needs the optional
pypdfium2 extra, which only the desktop app installs.
"""

import io

import pytest
from docsigner_core import SignerError, page_size, render_page

pytest.importorskip("pypdfium2", reason="needs the optional render extra")


@pytest.fixture(scope="module")
def protected_pdf(tmp_path_factory):
    """A one-page PDF nobody can open without the password."""
    from helpers_core import make_blank_pdf
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.pdf_utils.writer import copy_into_new_writer

    writer = copy_into_new_writer(PdfFileReader(io.BytesIO(make_blank_pdf())))
    writer.encrypt("owner-pass", "user-pass")
    out = io.BytesIO()
    writer.write(out)
    path = tmp_path_factory.mktemp("protected") / "locked.pdf"
    path.write_bytes(out.getvalue())
    return str(path)


READERS = [lambda p: render_page(p, -1), lambda p: page_size(p, -1)]


@pytest.mark.parametrize("read", READERS)
def test_protected_pdf_is_refused_in_plain_words(protected_pdf, read):
    with pytest.raises(SignerError) as caught:
        read(protected_pdf)
    assert caught.value.code == "DOCUMENT_INVALID"
    assert "password-protected" in caught.value.message
    assert "PDFium" not in caught.value.message


@pytest.mark.parametrize("read", READERS)
@pytest.mark.parametrize(
    "name,body,expected",
    [
        ("not-a-pdf.pdf", b"just some text\n", "damaged"),
        ("empty.pdf", b"", "damaged"),
        ("gone.pdf", None, "no longer there"),
    ],
)
def test_other_unreadable_files_also_get_a_sentence(tmp_path, read, name, body, expected):
    """Not only the password case: pdfium's "Data format error" was reaching the
    window too, and a deleted file arrived as a bare Python traceback."""
    path = tmp_path / name
    if body is not None:
        path.write_bytes(body)
    with pytest.raises(SignerError) as caught:
        read(str(path))
    assert expected in caught.value.message
    assert "PDFium" not in caught.value.message
    # The detail is not lost, only moved: the caller logs the cause.
    assert caught.value.__cause__ is not None


def test_a_readable_pdf_still_renders(tmp_path):
    from helpers_core import make_blank_pdf

    path = tmp_path / "plain.pdf"
    path.write_bytes(make_blank_pdf())
    assert render_page(str(path), -1)["pages"] == 1
