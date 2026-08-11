"""Spot a PDF/A file, so we can warn instead of quietly breaking it.

An invisible signature is safe on one. A visible stamp is not: the stamp font
is not embedded, and PDF/A forbids that.
"""

import io
import re

from pyhanko.pdf_utils.reader import PdfFileReader

_PART = re.compile(rb"pdfaid:part(?:>\s*|=\s*[\"'])(\d+)")
_CONFORMANCE = re.compile(rb"pdfaid:conformance(?:>\s*|=\s*[\"'])([A-Ua-u])")


def parse_xmp_pdfa(xmp: bytes):
    """Dig the PDF/A claim out of raw metadata. None if there is none."""
    part = _PART.search(xmp)
    if not part:
        return None
    conformance = _CONFORMANCE.search(xmp)
    return {
        "part": int(part.group(1)),
        "conformance": conformance.group(1).decode().upper() if conformance else None,
    }


def detect_pdfa(pdf_bytes: bytes):
    """What flavour of PDF/A this file claims to be. None if it is not one."""
    try:
        reader = PdfFileReader(io.BytesIO(pdf_bytes), strict=False)
        metadata = reader.root["/Metadata"].data
    except Exception:
        return None
    return parse_xmp_pdfa(metadata)
