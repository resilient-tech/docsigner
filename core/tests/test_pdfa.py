"""PDF/A identification from XMP metadata."""

from docsigner_core.pdfa import parse_xmp_pdfa

ELEMENT_FORM = b"""<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:Description xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/">
    <pdfaid:part>2</pdfaid:part><pdfaid:conformance>B</pdfaid:conformance>
  </rdf:Description></x:xmpmeta>"""

ATTRIBUTE_FORM = b'<rdf:Description pdfaid:part="3" pdfaid:conformance="u"/>'


def test_element_form():
    assert parse_xmp_pdfa(ELEMENT_FORM) == {"part": 2, "conformance": "B"}


def test_attribute_form_and_case():
    assert parse_xmp_pdfa(ATTRIBUTE_FORM) == {"part": 3, "conformance": "U"}


def test_not_pdfa():
    assert parse_xmp_pdfa(b"<x:xmpmeta>plain document metadata</x:xmpmeta>") is None
